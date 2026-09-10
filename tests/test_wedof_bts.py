import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from bts_workspace import register_bts_workspace
from bts_workspace_store import WorkspaceStore, billing_view
from tests.test_bts_workspace import make_legacy
from wedof_bts import FINANCER, WedofBtsClient, folder_fields, is_apprenticeship_event, normalize_summary, raw_fields
from wedof_bts_sync import sync_step
from wedof_service import WedofApiError


def contract(key=1, **changes):
    return {"id": key, "financer": FINANCER, "state": "accepted", "amount": 6000,
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
        self.assertEqual(http.get.call_args.kwargs['params'], {'financer': FINANCER, 'state': 'all', 'page': 1, 'limit': 1})
        self.assertEqual(reserve.call_args.kwargs['origin'], 'gestionstagiaires-bts')
        self.assertNotIn('allow_over_limit', reserve.call_args.kwargs)
        self.assertEqual(http.get.call_args.args[0], 'https://www.wedof.fr/api/workingContracts')

    def test_invalid_financer_or_identity_fails_closed(self):
        for item in (contract(financer='cpf'), contract(id='../organisms'), {'type': 'cpf'}, contract(id=True)):
            with self.assertRaises(WedofApiError):
                normalize_summary(item)
        http = Mock()
        http.get.return_value = self.response(contract(2))
        with patch('wedof_service.reserve_request'):
            with self.assertRaises(WedofApiError):
                WedofBtsClient(api_key='x', session=http).contract('1')

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


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.legacy = make_legacy(self.temp.name)
        self.store = WorkspaceStore(self.legacy.AKTO_BTS_DB_FILE)
        self.api = Mock()
        self.api.contracts_page.return_value = ([normalize_summary(contract())], False, 1)
        self.api.folder.return_value = folder_fields(folder(), 'OPCO-1')

    def step(self, **kwargs):
        return sync_step(self.store, self.api, 'Test', config_id='config', **kwargs)

    def finish(self, state):
        return self.step(run_id=state['id'], revision=state['revision'])

    def test_import_reimport_preserves_local_work_and_no_duplicates(self):
        local = self.store.create_local({'apprentice_first_name': 'Local', 'apprentice_last_name': 'Exemple'})
        state = self.step(action='start')
        self.assertEqual(state['added'], 1)
        self.assertEqual(state['phase'], 'details')
        state = self.finish(state)
        self.assertEqual(state['status'], 'complete')
        self.store.annotate('w-1', 'Suivi à conserver', ['cerfa_prepared'], 0, 'Test')
        self.store.add_fee('w-1', 'PREMIER_EQUIPEMENT', '150', 'Frais', 'Test')
        state = self.step(action='start')
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(state['unchanged'], 1)
        self.api.folder.assert_called_once()
        self.assertEqual(self.store.listing()['total'], 2)
        item = self.store.record('w-1')
        self.assertEqual(item['name'], 'Camille Exemple')
        self.assertEqual(item['annotation']['notes'], 'Suivi à conserver')
        self.assertEqual(item['fees'][0]['amount_cents'], 15000)
        self.assertIsNotNone(self.store.record(local))
        self.assertNotIn('PRIVATE', json.dumps(self.store.export_workspace()))

    def test_quota_pause_keeps_cursor_and_resume_retrieves_remaining(self):
        state = self.step(action='start')
        self.api.folder.side_effect = WedofApiError('Plafond atteint', 'wedof_quota_exceeded', False, 429)
        paused = self.finish(state)
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(self.store.wedof_state()['index'], 0)
        self.api.folder.side_effect = None
        done = self.step(action='resume')
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(done['details_done'], 1)
        self.api.contracts_page.assert_called_once()

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

    def test_retry_with_old_revision_does_not_issue_more_requests(self):
        state = self.step(action='start')
        done = self.finish(state)
        again = self.finish(state)
        self.assertEqual(again, done)
        self.api.folder.assert_called_once()

    def test_missing_folder_keeps_contract_and_flags_incomplete(self):
        state = self.step(action='start')
        self.api.folder.side_effect = WedofApiError('Introuvable', 'wedof_not_found', False, 404)
        done = self.finish(state)
        self.assertEqual(done['errors'], 1)
        self.assertEqual(done['status'], 'complete')
        self.assertTrue(self.store.record('w-1')['needs_detail'])
        self.assertEqual(self.store.record('w-1')['details_error'], 'Introuvable')

    def test_repeated_pages_stop_and_missing_contracts_are_not_deleted(self):
        self.api.contracts_page.return_value = ([normalize_summary(contract())], True, None)
        state = self.step(action='start')
        paused = self.finish(state)
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(self.store.listing()['total'], 1)
        self.api.contracts_page.return_value = ([], False, 0)
        done = self.step(action='resume')
        self.assertEqual(done['status'], 'complete')
        self.assertTrue(self.store.record('w-1')['missing_from_latest'])

    def test_routes_read_cache_only_and_write_permissions_csrf(self):
        register_bts_workspace(self.legacy)
        client = self.legacy.app.test_client()
        with patch.dict(os.environ, {'WEDOF_API_KEY': 'test-key'}), patch('bts_workspace.WedofBtsClient', return_value=self.api) as factory:
            self.assertEqual(client.post('/admin/BTS/wedof/synchroniser').status_code, 302)
            with client.session_transaction() as session:
                session.update(admin_logged_in=True, admin_role='admin')
            for path in ('/admin/BTS', '/admin/BTS/connexion'):
                self.assertEqual(client.get(path).status_code, 200)
            factory.assert_not_called()
            self.assertEqual(client.post('/admin/BTS/wedof/synchroniser').status_code, 400)
            with client.session_transaction() as session:
                token = session['bts_csrf_token']
            data = {'bts_csrf_token': token, 'action': 'start'}
            self.assertEqual(client.post('/admin/BTS/wedof/synchroniser', data={**data, 'action': 'invalid'}).status_code, 400)
            response = client.post('/admin/BTS/wedof/synchroniser', data=data, headers={'Accept': 'application/json'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['added'], 1)
            self.assertNotIn('config_id', response.json)
            for role in ('viewer', 'partner_admin'):
                with client.session_transaction() as session:
                    session['admin_role'] = role
                self.assertEqual(client.post('/admin/BTS/wedof/synchroniser', data=data).status_code, 403)


class RelayTests(unittest.TestCase):
    def test_known_opco_events_are_recognised_without_affecting_cpf(self):
        for payload in (folder(), {'financer': FINANCER}, {'event': 'workingContract.updated'},
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
