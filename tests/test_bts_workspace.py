"""No production credentials, real students or external API calls in these tests."""
import datetime as dt
import json
import re
import tempfile
import unittest
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, abort, redirect, session
from akto_bts import normalize_contract
from bts_workspace import register_bts_workspace
from bts_workspace_store import (
    EditConflict, WorkspaceError, WorkspaceStore, billing_view, money_cents, opco_costs_view,
    remote_id, remote_number, validate_fields,
)

ROOT = Path(__file__).resolve().parents[1]


def make_legacy(directory):
    app = Flask('bts-test', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(TESTING=True, SECRET_KEY='ephemeral-tests-only')
    app.add_url_rule('/admin/sessions', 'admin_sessions', lambda: 'sessions')
    app.add_url_rule('/admin/BTS', 'admin_bts', lambda: 'old workspace')
    def login_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('admin_logged_in'):
                return redirect('/login')
            return fn(*args, **kwargs)
        return wrapped
    def super_admin(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if session.get('partner_id') or session.get('admin_role') == 'partner_admin':
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    def write_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if session.get('admin_role') == 'viewer':
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return SimpleNamespace(app=app, AKTO_BTS_DB_FILE=str(Path(directory) / 'akto_bts.sqlite3'),
        AKTO_BTS_SYNC_LOCK_FILE=str(Path(directory) / 'akto.lock'),
        admin_login_required=login_required, require_super_admin=super_admin,
        admin_write_required=write_required, _akto_bts_sync_is_running=lambda: False,
        admin_bts_akto_sync=lambda: redirect('/admin/BTS'), PARTNER_SPACE_FORBIDDEN_ENDPOINTS=set())


def seed_remote(store, number='D-1'):
    data = {'cerfa': {'numeroInterne': number, 'numeroExterne': 'EX-01', 'etat': 'ENGAGE',
            'apprenti': {'prenom': 'Alice', 'nom': 'Test', 'courriel': 'alice@example.test'},
            'employeur': {'denomination': 'Entreprise de démonstration', 'siret': '12345678901234'},
            'formation': {'intituleQualification': 'BTS MOS'}, 'contrat': {'noContrat': 'DECA-TEST'}},
            'engagement': 4000, 'echeances': [
                {'numero': 1, 'codification': 'E1', 'montantTotal': 1000, 'montantRegle': 1000,
                 'montantEnCoursInstruction': 0, 'dateOuverture': '2020-01-01'},
                {'numero': 2, 'codification': 'E2', 'montantTotal': 1000, 'montantRegle': 0,
                 'montantEnCoursInstruction': 1000, 'dateOuverture': '2020-02-01'},
                {'numero': 3, 'codification': 'E3', 'montantTotal': 1000, 'montantRegle': 0,
                 'montantEnCoursInstruction': 0, 'dateOuverture': '2020-03-01'},
                {'numero': 4, 'codification': 'E4', 'montantTotal': 1000, 'montantRegle': 0,
                 'montantEnCoursInstruction': 0, 'dateOuverture': '2099-01-01'}]}
    store.start_run('seed-' + number)
    contract = normalize_contract({'numeroInterne': number, 'etat': 'ENGAGE'}, data, [], synced_at='2026-09-10T05:00:00Z', detail_loaded=True)
    store.replace_snapshot('seed-' + number, [contract], [], errors=[])
    return remote_id(number), data


class FinanceTests(unittest.TestCase):
    def test_periods_follow_consecutive_openings_without_inventing_a_final_end(self):
        record = {'contract_end': '2028-08-31', 'schedules': [
            {'numero': 3, 'dateOuverture': '2027-06-01'},
            {'numero': 1, 'dateOuverture': '2026-09-01'},
            {'numero': 2, 'dateOuverture': '2027-03-01'},
            {'numero': 4, 'dateOuverture': '2028-09-01'}]}
        original = json.dumps(record)
        cards = billing_view(record)['cards']
        self.assertEqual([(c['period_start'], c['period_end']) for c in cards[:2]],
                         [('2026-09-01', '2027-03-01'), ('2027-03-01', '2027-06-01')])
        self.assertTrue(cards[-1]['last_opening'])
        self.assertEqual(cards[-1]['period_start'], '2028-09-01')
        self.assertEqual(cards[-1]['period_end'], '')
        self.assertEqual(json.dumps(record), original)

    def test_periods_preserve_opco_dates_and_do_not_bridge_missing_or_invalid_openings(self):
        cards = billing_view({'schedules': [
            {'numero': 1, 'dateOuverture': '2026-09-01', 'dateDebut': '2026-08-20', 'dateFin': '2027-02-28'},
            {'numero': 2, 'dateOuverture': '2027-03-01'},
            {'numero': 3, 'dateOuverture': None},
            {'numero': 4, 'dateOuverture': '2027-06-01'},
            {'numero': 5, 'dateOuverture': '2026-06-01'}]})['cards']
        self.assertEqual(cards[0]['period_origin'], 'opco')
        self.assertEqual(cards[0]['period_end'], '2027-02-28')
        self.assertEqual(cards[1]['period_end'], '')
        self.assertEqual(cards[3]['period_end'], '')
        self.assertTrue(cards[3]['period_issue'])
        duplicate = billing_view({'schedules': [{'numero': n, 'dateOuverture': '2027-03-01'} for n in (1, 2)]})['cards']
        self.assertTrue(all(c['period_issue'] and not c['period_end'] for c in duplicate))

    def test_fee_payments_use_grants_and_settlement_flags_never_ceilings_or_tuition(self):
        record = {'source': 'wedof', 'extra_costs_available': True, 'billing_details_available': True,
                  'extra_costs': [{'natureFrais': 'Premierequipement', 'montantTotal': 500},
                                  {'natureFrais': 'Restauration', 'montantTotal': 600}],
                  'billing_details': {'plafondFraisPremierEquipement': 3500, 'fraisPremierEquipementRegles': False},
                  'schedules': [{'numero': 1, 'montantRegle': 100}]}
        items = opco_costs_view(record)['items']
        self.assertEqual(items[0]['amount'], 50000)
        self.assertEqual(items[0]['status_label'], 'Non soldé')
        self.assertIsNone(items[0]['paid'])  # False does not rule out a partial payment.
        self.assertIsNone(items[0]['outstanding'])
        self.assertEqual(items[1]['status_label'], 'Règlement non communiqué')
        record['billing_details']['fraisPremierEquipementRegles'] = True
        record['extra_costs'].append({'natureFrais': 'PREMIER_EQUIPEMENT', 'montantTotal': 50})
        items = opco_costs_view(record)['items']
        self.assertEqual(len(items), 2)
        self.assertEqual((items[0]['paid'], items[0]['outstanding']), (55000, 0))
        self.assertIsNone(items[1]['paid'])
        record['raw_stale'] = True
        self.assertIsNone(opco_costs_view(record)['items'][0]['paid'])
        self.assertEqual(opco_costs_view(record)['items'][0]['status_label'], 'À actualiser')

    def test_decimal_rounding_and_bad_values(self):
        self.assertEqual(money_cents('1 250,55'), 125055)
        self.assertEqual(money_cents('1.005'), 101)
        for value in ('NaN', 'Infinity', '', None, 'bad'):
            self.assertIsNone(money_cents(value))
            with self.assertRaises(WorkspaceError):
                money_cents(value, strict=True)

    def test_partial_payments_are_partitioned_without_double_counting(self):
        result = billing_view({'schedules': [{'numero': 1, 'montantTotal': 1000,
            'montantRegle': 200, 'montantEnCoursInstruction': 300, 'dateOuverture': '2020-01-01'}]})
        self.assertEqual(result['total'], 100000)
        self.assertEqual({item['key']: item['amount'] for item in result['legend']},
                         {'paid': 20000, 'pending': 30000, 'due': 50000, 'future': 0, 'unknown': 0})
        self.assertEqual(result['cards'][0]['remaining'], 50000)

    def test_incomplete_overpaid_and_duplicate_schedules_cannot_be_drafted(self):
        for schedule in (
            {'numero': 1, 'montantTotal': 1000},
            {'numero': 1, 'montantTotal': 1000, 'montantRegle': 1200, 'montantEnCoursInstruction': 0},
            {'numero': 1, 'montantTotal': 1000, 'montantRegle': 0, 'montantEnCoursInstruction': 0},
        ):
            self.assertFalse(billing_view({'schedules': [schedule]})['cards'][0]['can_draft'])
        good = {'numero': 1, 'codification': 'x', 'montantTotal': 10, 'montantRegle': 0,
                'montantEnCoursInstruction': 0, 'dateOuverture': '2020-01-01'}
        self.assertTrue(all(not card['can_draft'] for card in billing_view({'schedules': [good, good]})['cards']))

    def test_validation_and_identifiers(self):
        base = {'apprentice_first_name': 'A', 'apprentice_last_name': 'B'}
        for bad in ({'employer_siret': '123'}, {'apprentice_email': 'bad'},
                    {'training_hours': '2', 'remote_hours': '3'},
                    {'contract_start': '2026-09-10', 'contract_end': '2026-09-09'},
                    {'training_hours': '1.5'}):
            with self.assertRaises(WorkspaceError):
                validate_fields(dict(base, **bad))
        self.assertEqual(validate_fields(dict(base, training_hours='1 350'))['training_hours'], '1350')
        self.assertEqual(remote_number(remote_id('AKTO/numéro 123')), 'AKTO/numéro 123')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(str(Path(self.directory.name) / 'akto_bts.sqlite3'))
        self.local = self.store.create_local({'apprentice_first_name': 'Camille', 'apprentice_last_name': 'Test'})
    def tearDown(self):
        self.directory.cleanup()

    def test_create_edit_conflict_and_unknown_fields(self):
        self.store.save_fields(self.local, {'apprentice_email': 'c@example.test', 'nir': 'secret'}, 1, 'Test')
        self.assertEqual(self.store.record(self.local)['apprentice_email'], 'c@example.test')
        self.assertNotIn('nir', self.store.record(self.local))
        with self.assertRaises(EditConflict):
            self.store.save_fields(self.local, {'apprentice_email': 'other@example.test'}, 1, 'Test')

    def test_notes_fees_drafts_survive_akto_snapshot(self):
        self.store.annotate(self.local, 'Note locale', ['cerfa_prepared'], 0, 'Test')
        self.store.add_fee(self.local, 'RESTAURATION', '60,55', 'Repas', 'Test')
        self.store.create_invoice_draft(self.local, 'entreprise', '', '150', 'Prestation vérifiée', 'Test')
        remote, _ = seed_remote(self.store)
        record = self.store.record(self.local)
        self.assertEqual(record['fees'][0]['amount_cents'], 6055)
        self.assertEqual(len(record['drafts']), 1)
        self.assertEqual(record['annotation']['notes'], 'Note locale')
        with self.assertRaises(EditConflict):
            self.store.annotate(self.local, 'Perte interdite', [], 0, 'Test')
        with self.assertRaises(WorkspaceError):
            self.store.save_fields(remote, {'apprentice_first_name': 'Wrong'}, 0, 'Test')

    def test_invoice_duplicates_paid_and_future_blocked(self):
        remote, _ = seed_remote(self.store)
        self.store.create_invoice_draft(remote, 'opco', 'code:E3', '0.01', 'tampered', 'Test')
        self.assertEqual(self.store.record(remote)['drafts'][0]['amount_cents'], 100000)
        for key in ('code:E1', 'code:E2', 'code:E3', 'code:E4', 'missing'):
            with self.assertRaises(WorkspaceError):
                self.store.create_invoice_draft(remote, 'opco', key, '1', 'bad', 'Test')

    def test_targeted_refresh_keeps_other_work_and_checks_identity(self):
        remote, detail = seed_remote(self.store)
        self.store.annotate(remote, 'À rappeler', [], 0, 'Test')
        detail['echeances'][2]['montantRegle'] = 500
        self.store.update_remote_detail('D-1', detail, 'Test')
        self.assertEqual(self.store.record(remote)['schedules'][2]['montantRegle'], 500)
        self.assertIsNotNone(self.store.record(self.local))
        detail['cerfa']['numeroInterne'] = 'WRONG'
        with self.assertRaises(WorkspaceError):
            self.store.update_remote_detail('D-1', detail, 'Test')
        self.assertEqual(self.store.record(remote)['annotation']['notes'], 'À rappeler')

    def test_item_ownership_and_pagination(self):
        second = self.store.create_local({'apprentice_first_name': 'Other', 'apprentice_last_name': 'Test'})
        draft = self.store.create_invoice_draft(self.local, 'entreprise', '', '10', 'Test', 'Test')
        with self.assertRaises(WorkspaceError):
            self.store.remove_local_item(second, draft, 'draft', 'Test')
        self.store.remove_local_item(self.local, draft, 'draft', 'Test')
        self.assertEqual(self.store.listing('Camille')['total'], 1)
        self.assertEqual(self.store.listing("' OR 1=1 --")['total'], 0)
        self.assertEqual(self.store.listing(page=999, per_page=1)['page'], 2)
        self.assertEqual(len(self.store.export_workspace()['bts_local_dossiers']), 2)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.legacy = make_legacy(self.directory.name)
        register_bts_workspace(self.legacy)
        self.client = self.legacy.app.test_client()
        self.store = WorkspaceStore(self.legacy.AKTO_BTS_DB_FILE)
        self.remote, _ = seed_remote(self.store)
        self.local = self.store.create_local({'apprentice_first_name': '<script>alert(1)</script>', 'apprentice_last_name': 'Test'})
        with self.client.session_transaction() as state:
            state.update(admin_logged_in=True, admin_role='admin', bts_csrf_token='test-token')
        self.csrf = {'bts_csrf_token': 'test-token'}
    def tearDown(self):
        self.directory.cleanup()

    def test_all_screens_render_without_context_processors_or_api_calls(self):
        @self.legacy.app.context_processor
        def forbidden_legacy_processor():
            raise AssertionError('BTS must not run data.json navigation context processors')
        paths = ['/admin/BTS', '/admin/BTS/nouveau', '/admin/BTS/connexion']
        paths += [f'/admin/BTS/dossiers/{self.remote}?tab={tab}' for tab in ('suivi','etudiant','entreprise','contrat','gestion','comptabilite')]
        paths += [f'/admin/BTS/dossiers/{self.local}?tab={tab}' for tab in ('etudiant','entreprise','contrat','gestion','comptabilite')]
        paths += [f'/admin/BTS/dossiers/{self.local}?tab=comptabilite&payer=entreprise']
        with patch('bts_workspace.AktoClient', side_effect=AssertionError('GET must not call AKTO')):
            for path in paths:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertNotIn('<script>alert(1)</script>', response.get_data(as_text=True))

    def test_csrf_authentication_and_partner_isolation(self):
        self.assertEqual(self.client.post('/admin/BTS/nouveau', data={}).status_code, 400)
        with self.client.session_transaction() as state:
            state['admin_role'] = 'viewer'
        self.assertEqual(self.client.post('/admin/BTS/nouveau', data=self.csrf).status_code, 403)
        with self.client.session_transaction() as state:
            state['partner_id'] = 'other-school'
        for path in ('/admin/BTS', '/admin/BTS/export.json', '/admin/BTS/connexion', '/admin/BTS/dossiers/' + self.remote):
            self.assertEqual(self.client.get(path).status_code, 403)
        with self.client.session_transaction() as state:
            state.clear()
        self.assertEqual(self.client.get('/admin/BTS').status_code, 302)

    def test_create_edit_fee_notes_enterprise_draft_and_export(self):
        response = self.client.post('/admin/BTS/nouveau', data=dict(self.csrf, apprentice_first_name='Élodie', apprentice_last_name='Test'))
        self.assertEqual(response.status_code, 302)
        record_id = response.headers['Location'].split('/dossiers/')[1].split('?')[0]
        base = '/admin/BTS/dossiers/' + record_id
        response = self.client.post(base + '/frais', data=dict(self.csrf, nature='HEBERGEMENT', amount='80', description='Test'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.store.record(record_id)['fees'][0]['amount_cents'], 8000)
        self.client.post(base + '/brouillons', data=dict(self.csrf, payer='entreprise', amount='150', description='Test'))
        self.client.post(base + '/suivi', data=dict(self.csrf, revision='0', notes='Note', checked=['cerfa_prepared']))
        self.assertEqual(self.store.record(record_id)['annotation']['notes'], 'Note')
        self.assertEqual(self.client.get('/admin/BTS/export.json').status_code, 200)
        self.assertEqual(self.client.get(base + '/brouillons/unknown.json').status_code, 404)


if __name__ == '__main__':
    unittest.main()
