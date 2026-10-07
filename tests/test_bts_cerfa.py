"""Synthetic CERFA fixtures only: no real identities or external API calls."""
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from bts_cerfa import (FIELDS, PRIVATE_FIELDS, CerfaValidationError, cerfa_view, effective_values,
                       prefill_opco, readiness, source_version, validate_values)
from bts_cerfa_pdf import RESERVED, TEMPLATE, CerfaPdfError, generate_pdf, pdf_values
from bts_workspace import register_bts_workspace
from bts_workspace_store import EditConflict, WorkspaceStore
from tests.test_bts_workspace import make_legacy, seed_remote


def complete_values():
    values = {
        'apprentice_first_name': 'Élodie', 'apprentice_last_name': 'EXEMPLE', 'apprentice_usage_name': 'TEST',
        'apprentice_birth_date': '2009-06-12', 'apprentice_nir': '2090683123456', 'apprentice_sex': 'F',
        'apprentice_birth_department': '083', 'apprentice_birth_city': 'Fréjus', 'apprentice_nationality': '1',
        'apprentice_social_regime': '2', 'apprentice_phone': '0600000000', 'apprentice_email': 'elodie@example.test',
        'apprentice_previous_situation': '1', 'apprentice_previous_diploma': '42', 'apprentice_previous_class': '01',
        'apprentice_previous_diploma_title': 'Baccalauréat général', 'apprentice_highest_diploma': '42',
        'apprentice_high_level_athlete': 'no', 'apprentice_rqth': 'no', 'apprentice_rqth_young': 'no',
        'apprentice_rqth_boe': 'yes', 'apprentice_business_project': 'no', 'apprentice_emancipated': 'no',
        'guardian_name': 'EXEMPLE Camille', 'guardian_email': 'parent@example.test',
        'employer_name': 'SOCIÉTÉ EXEMPLE', 'employer_siret': '12345678901234', 'employer_sector': 'private',
        'employer_type': '12', 'employer_specific': '0', 'employer_ape': '8010Z', 'employer_headcount': '42',
        'employer_idcc': '1351', 'employer_phone': '0400000000', 'employer_email': 'employeur@example.test',
        'pension_fund': 'AGIRC-ARRCO', 'training_title': 'MANAGEMENT OPÉRATIONNEL DE LA SÉCURITÉ',
        'rncp': 'RNCP41000', 'diploma_code': '32034401', 'training_diploma_type': '54',
        'training_start': '2026-09-01', 'training_end': '2030-06-30', 'exam_end': '2030-07-03',
        'training_hours': '2700', 'remote_hours': '150', 'contract_mode': '1', 'contract_type': '36',
        'contract_derogation': '22', 'previous_contract_number': 'PRECEDENT-EXEMPLE',
        'contract_conclusion': '2026-08-20', 'contract_start': '2026-09-01', 'contract_end': '2030-08-31',
        'practical_start': '2026-09-03', 'amendment_date': '2026-09-01', 'weekly_hours': '35', 'weekly_minutes': '30',
        'hazardous_work': 'no', 'gross_salary': '802.82', 'benefit_food': '3.25', 'benefit_housing': '120.75',
        'benefit_other': 'yes', 'cfa_company': 'no', 'cfa_name': 'CFA EXEMPLE', 'cfa_uai': '0830001A',
        'cfa_siret': '12345678900011', 'cfa_same_site': 'no', 'site_name': 'CAMPUS EXEMPLE',
        'site_uai': '0830002B', 'site_siret': '12345678900022', 'signing_city': 'Puget-sur-Argens',
        'tutor_attestation': 'yes', 'documents_attestation': 'yes',
    }
    for prefix in ('apprentice', 'employer', 'guardian', 'cfa', 'site'):
        values.update({prefix + '_address': '12 bis avenue de la République', prefix + '_address_complement': 'Bâtiment B',
                       prefix + '_postcode': '83600', prefix + '_city': 'Fréjus'})
    for prefix in ('tutor', 'tutor2'):
        values.update({prefix + '_last_name': 'DUPONT', prefix + '_first_name': 'François', prefix + '_birth_date': '1980-02-13',
                       prefix + '_email': prefix + '@example.test', prefix + '_job': 'Responsable de service',
                       prefix + '_diploma': 'BTS management', prefix + '_level': '5'})
    for year in range(1, 5):
        calendar_year = 2025 + year
        march = dt.date(calendar_year + 1, 3, 1)
        for period, start, end in ((1, f'{calendar_year}-09-01', (march-dt.timedelta(days=1)).isoformat()),
                                   (2, march.isoformat(), f'{calendar_year+1}-08-31')):
            values.update({f'salary_{year}_{period}_start': start, f'salary_{year}_{period}_end': end,
                           f'salary_{year}_{period}_rate': str(40 + year * 10 + period), f'salary_{year}_{period}_basis': 'SMIC'})
    return validate_values(values)


class PdfTests(unittest.TestCase):
    def test_all_216_canonical_fields_widgets_and_appearances(self):
        values = complete_values()
        self.assertFalse(readiness(values))
        expected, _ = pdf_values(values)
        original = PdfReader(TEMPLATE)
        self.assertEqual(set(original.get_fields()), set(expected) | RESERVED)
        reader = PdfReader(io.BytesIO(generate_pdf(values)))
        fields = reader.get_fields()
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual(len(fields), 216)
        self.assertFalse(reader.trailer['/Root']['/AcroForm']['/NeedAppearances'].value)
        for name, value in expected.items():
            self.assertEqual(str(fields[name].get('/V', '')), value, name)
        self.assertTrue(all(not fields[k].get('/V') for k in RESERVED))
        seen = []
        for page in reader.pages:
            for ref in page['/Annots']:
                widget = ref.get_object()
                name = widget['/T']
                seen.append(name)
                self.assertEqual(str(widget.get('/V', '')), str(fields[name].get('/V', '')), name)
                appearance = widget['/AP']['/N']
                if widget['/FT'] == '/Btn':
                    self.assertEqual(widget['/AS'], widget['/V'])
                    self.assertTrue(appearance[widget['/AS']].get_data())
                else:
                    self.assertTrue(appearance.get_data(), name)
        self.assertEqual(len(set(seen)), 216)
        # Independent checks on semantically important positions, not just a mirrored mapping.
        self.assertEqual(fields['Zone de texte 8_17']['/V'], 'Élodie')
        self.assertEqual(fields['Zone de texte 8_72']['/V'], '802')
        self.assertEqual(fields['Zone de texte 21_73']['/V'], '82')
        self.assertEqual(fields['Zone de texte 21_75']['/V'], '3')
        self.assertEqual(fields['Zone de texte 21_76']['/V'], '25')
        self.assertEqual(fields['Zone de texte 21_28']['/V'], '03')  # Exam end, not training end.
        self.assertEqual(fields['Zone de texte 8_76']['/V'], '41000')
        self.assertEqual(fields['Case #C3#A0 cocher 4']['/V'], '/Yes')
        self.assertEqual(fields['Case #C3#A0 cocher 3']['/V'], '/Off')
        self.assertEqual(fields['Zone de texte 21_81']['/V'], '01')
        self.assertEqual(fields['Zone de texte 21_72']['/V'], '2030')

    def test_optional_data_cleared_when_conditions_change_and_attestations_not_invented(self):
        values = complete_values()
        values.update(apprentice_birth_date='2000-01-01', cfa_same_site='yes', apprentice_rqth='yes',
                      contract_type='11', employer_unemployment='yes', tutor_attestation='', documents_attestation='')
        mapped, _ = pdf_values(values)
        self.assertFalse(mapped['Zone de texte 8_35'])  # Former legal guardian.
        self.assertFalse(mapped['Zone de texte 8_101'])  # Former separate site.
        self.assertFalse(mapped['Zone de texte 21_13'])  # Former amendment.
        self.assertFalse(mapped['Zone de texte 8_55'])  # Former contract reference.
        self.assertEqual(mapped['Case #C3#A0 cocher 5_8'], '/Off')
        for name in ('Case #C3#A0 cocher 6', 'Case #C3#A0 cocher 8', 'Case #C3#A0 cocher 2_2'):
            self.assertEqual(mapped[name], '/Off')

    def test_missing_data_is_blank_and_unprintable_long_text_is_rejected(self):
        mapped, _ = pdf_values({})
        self.assertTrue(all(value in ('', '/Off') for value in mapped.values()))
        with self.assertRaises(CerfaPdfError):
            generate_pdf({'training_title': 'W' * 150})
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / 'wrong.pdf'
            bad.write_bytes(b'not the supplied CERFA')
            with patch('bts_cerfa_pdf.TEMPLATE', bad), self.assertRaises(CerfaPdfError):
                generate_pdf({})

    def test_readiness_and_validation_cover_partial_salary_dates_codes_and_minor(self):
        values = complete_values()
        values['salary_1_2_start'] = '2027-03-10'
        self.assertIn('salary_1_2_start', readiness(values))
        values['guardian_name'] = ''
        self.assertIn('guardian_name', readiness(values))
        values['apprentice_emancipated'] = 'yes'
        self.assertNotIn('guardian_name', readiness(values))
        values['remote_hours'] = '3000'
        self.assertIn('remote_hours', readiness(values))
        for entry in ({'weekly_minutes': '60'}, {'contract_start': '2026-02-30'}, {'employer_type': 'invalid'},
                      {'apprentice_nir': 'bad'}, {'gross_salary': 'nan'}, {'salary_1_1_rate': '-1'}):
            with self.subTest(entry=entry), self.assertRaises(CerfaValidationError):
                validate_values(entry)
        self.assertEqual(validate_values({'gross_salary': '802,82'})['gross_salary'], '802.82')

    def test_optional_opco_defaults_reuse_tutor_and_salary_but_exclude_sensitive_and_attestations(self):
        source = {'apprenti': {'sexe': 'F', 'nomUsage': 'Test', 'nir': '2090683123456', 'handicap': True,
                              'responsableLegal': {'nom': 'EXEMPLE', 'prenom': 'Camille', 'courriel': 'parent@example.test',
                                                   'adresse': {'adresse1': '12 rue Test', 'adresse2': 'Bâtiment B', 'codePostal': '83600', 'commune': 'Fréjus'}}},
                  'maitre1': {'prenom': 'François', 'nom': 'Dupont', 'dateNaissance': '1980-02-13T00:00:00Z'},
                  'employeur': {'typeEmployeur': 12, 'attestationEligibilite': True, 'naf': '80.10Z', 'codeIdcc': 43,
                                'adresse': {'numero': '12', 'voie': 'rue Test', 'complement': 'Bâtiment B'}},
                  'contrat': {'remunerationsAnnuelles': [{'ordre': '1.1', 'dateDebut': '2026-09-01', 'taux': 43, 'typeSalaire': 'SMIC'}]}}
        defaults = prefill_opco(source)
        self.assertEqual(defaults['tutor_first_name'], 'François')
        self.assertEqual(defaults['tutor_birth_date'], '1980-02-13')
        self.assertEqual(defaults['salary_1_1_rate'], '43')
        self.assertEqual(defaults['employer_sector'], 'private')
        self.assertEqual(defaults['employer_idcc'], '0043')
        self.assertEqual(defaults['guardian_name'], 'EXEMPLE Camille')
        self.assertEqual(defaults['guardian_address'], '12 rue Test')
        self.assertEqual(defaults['guardian_address_complement'], 'Bâtiment B')
        self.assertFalse(set(defaults) & (PRIVATE_FIELDS | {'tutor_attestation', 'documents_attestation'}))
        record = {'cerfa_prefill': defaults, 'employer_address': '12 rue Test Bâtiment B'}
        self.assertEqual(effective_values(record, {})['employer_address'], '12 rue Test')
        self.assertEqual(effective_values({'source_payload': {'cerfa': source}}, {})['tutor_first_name'], 'François')
        for malformed in (None, [], {'apprenti': 'bad', 'contrat': 3}, {'contrat': {'remunerationsAnnuelles': 3}}):
            self.assertEqual(prefill_opco(malformed), {})


class StoreAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.legacy = make_legacy(self.directory.name)
        register_bts_workspace(self.legacy)
        self.store = WorkspaceStore(self.legacy.AKTO_BTS_DB_FILE)
        self.id, self.source = seed_remote(self.store)
        self.base = '/admin/BTS/dossiers/' + self.id
        self.client = self.legacy.app.test_client()
        with self.client.session_transaction() as state:
            state.update(admin_logged_in=True, admin_role='admin')
        self.client.get(self.base + '?tab=contrat')
        with self.client.session_transaction() as state:
            self.csrf = {'bts_csrf_token': state['bts_csrf_token']}

    def test_complements_survive_refresh_and_do_not_overwrite_source_or_export_nir(self):
        record = self.store.record(self.id)
        self.store.save_cerfa_complements(self.id, {'apprentice_nir': '2090683123456', 'training_title': 'Titre corrigé'},
                                          0, source_version(record), 'Test')
        self.assertEqual(self.store.record(self.id)['training_title'], 'BTS MOS')
        self.source['cerfa']['formation']['intituleQualification'] = 'Titre OPCO actualisé'
        self.store.update_remote_detail('D-1', self.source, 'Test')
        self.assertEqual(effective_values(self.store.record(self.id), self.store.cerfa_complements(self.id)['values'])['training_title'], 'Titre corrigé')
        self.assertNotIn('2090683123456', json.dumps(self.store.export_workspace()))
        self.assertNotIn('2090683123456', json.dumps(self.store.record(self.id)['events']))
        with self.assertRaises(EditConflict):
            self.store.save_cerfa_complements(self.id, {'signing_city': 'Paris'}, 0, source_version(record), 'Test')

    def test_local_basics_saved_and_independent_dossiers_isolated(self):
        key = self.store.create_local({'apprentice_first_name': 'Alice', 'apprentice_last_name': 'Test'})
        self.store.save_cerfa_complements(key, {'apprentice_first_name': 'Camille', 'apprentice_nir': '2090683123456'},
                                          0, source_version(self.store.record(key)), 'Test')
        self.assertEqual(self.store.record(key)['apprentice_first_name'], 'Camille')
        self.assertNotIn('apprentice_nir', self.store.record(key))
        self.assertEqual(self.store.cerfa_complements(self.id)['values'], {})

    def test_pdf_and_form_routes_are_protected_no_cache_and_do_not_call_wedof(self):
        with patch('bts_workspace.WedofBtsClient', side_effect=AssertionError('No remote call')):
            response = self.client.get(self.base + '/cerfa.pdf?download=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(self.client.post(self.base + '/cerfa/enregistrer', data={}).status_code, 400)
        with self.client.session_transaction() as state:
            state['admin_role'] = 'viewer'
        self.assertEqual(self.client.post(self.base + '/cerfa/enregistrer', data=self.csrf).status_code, 403)
        with self.client.session_transaction() as state:
            state['partner_id'] = 'partner'
        self.assertEqual(self.client.get(self.base + '/cerfa.pdf').status_code, 403)
        with self.client.session_transaction() as state:
            state.clear()
        self.assertEqual(self.client.get(self.base + '/cerfa.pdf').status_code, 302)

    def test_invalid_submission_keeps_inputs_and_concurrent_source_change_returns_conflict(self):
        version = source_version(self.store.record(self.id))
        data = {**self.csrf, 'tab': 'entreprise', 'revision': '0', 'source_version': version,
                'employer_name': 'Saisie conservée', 'employer_type': 'not-an-enum'}
        response = self.client.post(self.base + '/cerfa/enregistrer', data=data)
        self.assertEqual(response.status_code, 422)
        self.assertIn('Saisie conservée', response.text)
        self.assertIn('Choisissez une valeur', response.text)
        self.assertEqual(self.store.cerfa_complements(self.id)['revision'], 0)
        self.source['cerfa']['formation']['intituleQualification'] = 'Formation actualisée'
        self.store.update_remote_detail('D-1', self.source, 'Test')
        data.update(employer_type='12')
        response = self.client.post(self.base + '/cerfa/enregistrer', data=data)
        self.assertEqual(response.status_code, 409)


if __name__ == '__main__':
    unittest.main()
