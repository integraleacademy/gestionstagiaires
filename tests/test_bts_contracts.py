"""Synthetic identities, local documents and fake APIs only; never sends anything."""
import copy
import datetime as dt
import hashlib
import io
import json
import shutil
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from bts_cerfa import effective_values, source_version
from bts_contract_documents import (defaults, needs_guardian, validate_settings,
    fill_convention, prepare_cerfa, generate_documents, fingerprint)
from bts_contract_store import ContractStore
from bts_contract_yousign import send_signature, refresh_signature, SignatureError
from bts_contract_wedof import build_cerfa, advance_submission, check_submission, nir_with_key
from bts_workspace import register_bts_workspace
from bts_workspace_store import WorkspaceError
from wedof_service import WedofApiError
from tests.test_bts_cerfa import complete_values
from tests.test_bts_workspace import make_legacy


def settings(values, mode='presentiel'):
    return defaults(values, dict(teaching_mode=mode, employer_first_name='Alex', employer_last_name='EXEMPLE',
        guardian_first_name='Camille', guardian_last_name='EXEMPLE', financer='opcoCfaAkto',
        npec_1='8000', npec_2='8000', rac_1='0', rac_2='750', convention_date='2026-09-14'))


def assets():
    with zipfile.ZipFile(Path(__file__).resolve().parents[1] / 'templates_word/tableau_suivi_foad_cnaps.docx') as z:
        return {'stamp': z.read('word/media/image2.png'), 'signature': z.read('word/media/image3.png')}


def fake_package(store, mode='presentiel'):
    values = complete_values()
    values['apprentice_birth_date'] = (dt.date.today().replace(year=dt.date.today().year - 16)).isoformat()
    data = settings(values, mode)
    key = uuid.uuid4().hex
    store.path(key).mkdir()
    package = dict(id=key, created_at='2026-09-14T12:00:00Z', values=values, settings=data,
        documents={}, signature={}, opco={}, fingerprint=fingerprint(values, data))
    writer = PdfWriter(); writer.add_blank_page(595, 842)
    buf = io.BytesIO(); writer.write(buf)
    for kind in ('cerfa', 'formation', 'mobilite') if mode == 'presentiel' else ('cerfa', 'formation'):
        relative = key + '/' + kind + '.pdf'; store.path(relative).write_bytes(buf.getvalue())
        roles = ('employer',) if kind == 'formation' else ('employer', 'apprentice', 'guardian')
        package['documents'][kind] = dict(pdf=relative, sha256=hashlib.sha256(buf.getvalue()).hexdigest(),
            fields=[dict(role=r, type='signature', page=1, x=20+170*i, y=700, width=150, height=45) for i,r in enumerate(roles)])
    return package


class FakeYousign:
    def __init__(self, store, package, exclusions=True):
        self.store, self.package, self.exclusions = store, package, exclusions
        self.request_id = str(uuid.uuid4()); self.docs = []; self.people = []; self.calls = []; self.status = 'draft'

    def call(self, method, path, **kw):
        self.calls.append((method,path,copy.deepcopy(kw.get('json'))))
        if method == 'POST' and path == '/signature_requests':
            self.external = kw['json']['external_id']; return {'id': self.request_id, 'status': 'draft'}
        if method == 'POST' and path.endswith('/documents'):
            d = {'id':str(uuid.uuid4())}; self.docs.append(d); return d
        if method == 'POST' and path.endswith('/signers'):
            d = dict(kw['json'], id=str(uuid.uuid4()), status='initiated')
            if not self.exclusions: d.pop('excluded_documents', None)
            self.people.append(d); return d
        if method == 'GET' and path.endswith('/documents'): return self.docs
        if method == 'GET' and path.endswith('/signers'): return self.people
        if method == 'POST' and path.endswith('/activate'):
            self.status = 'ongoing'; return {'id':self.request_id, 'status':self.status}
        if method == 'GET' and path.endswith('/download'):
            doc_id = path.split('/')[-2]
            kind = next(k for k,v in self.package['signature']['documents'].items() if v == doc_id)
            return self.store.path(self.package['documents'][kind]['pdf']).read_bytes()
        if method == 'GET' and path.endswith(self.request_id):
            return dict(id=self.request_id, external_id=self.external, status=self.status)
        raise AssertionError((method,path))


class FakeWedof:
    def __init__(self): self.calls=[]; self.sent=False
    def call(self, method, path, payload=None, params=None):
        self.calls.append((method,path,copy.deepcopy(payload),params))
        if path.startswith('/certifications'): return ['123456']
        if method == 'GET' and path.startswith('/attendees/'): raise WedofApiError('Absent', http_status=404)
        if path == '/registrationFolders': return {'externalId':'TEST-FOLDER', 'type':'opcoCfa'}
        if path.endswith('/submit'):
            if not params: self.sent=True
            return {'id': 17, 'financer':'opcoCfaAkto', 'state':'sent' if self.sent else 'draft', 'externalIdTrainingOrganism':'TEST-OPCO'}
        if method == 'GET' and path == '/workingContracts/17':
            return {'id':17, 'financer':'opcoCfaAkto', 'state':'sent' if self.sent else 'draft'}
        return {'id':17}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=ContractStore(Path(self.tmp.name)/'bts.sqlite'); self.rid='l-test'
        self.package=fake_package(self.store)

    def signed(self):
        api=FakeYousign(self.store,self.package)
        send_signature(self.store,self.rid,self.package,api,'Test')
        api.status='done'
        for p in api.people: p['status']='signed'
        refresh_signature(self.store,self.rid,self.package,api)
        return api

    def test_one_request_one_signer_each_and_formation_excluded_from_apprentice_and_guardian(self):
        api=FakeYousign(self.store,self.package)
        send_signature(self.store,self.rid,self.package,api,'Test')
        self.assertEqual(len([c for c in api.calls if c[:2]==('POST','/signature_requests')]),1)
        self.assertEqual(len(api.docs),3); self.assertEqual(len(api.people),3)
        formation=self.package['signature']['documents']['formation']
        self.assertEqual([len(p['fields']) for p in api.people],[3,2,2])
        self.assertFalse(api.people[0].get('excluded_documents'))
        self.assertEqual(api.people[1]['excluded_documents'],[formation])
        self.assertEqual(api.people[2]['excluded_documents'],[formation])
        self.assertEqual(api.calls[-1][1].split('/')[-1],'activate')
        before=len(api.calls)
        with self.assertRaises(WorkspaceError): send_signature(self.store,self.rid,self.package,api,'Test')
        self.assertEqual(len(api.calls),before)

    def test_document_visibility_failure_prevents_activation(self):
        api=FakeYousign(self.store,self.package,exclusions=False)
        with self.assertRaises(SignatureError): send_signature(self.store,self.rid,self.package,api,'Test')
        self.assertFalse(any(c[1].endswith('/activate') for c in api.calls))

    def test_timeout_is_checkpointed_and_blocks_duplicate_creation(self):
        api=FakeYousign(self.store,self.package)
        with patch.object(api,'call',side_effect=SignatureError('Timeout',ambiguous=True)) as call:
            with self.assertRaises(SignatureError): send_signature(self.store,self.rid,self.package,api,'Test')
            restored=self.store.package(self.rid)
            self.assertEqual(restored['signature']['pending'],'create')
            with self.assertRaises(WorkspaceError): send_signature(self.store,self.rid,restored,api,'Test')
            self.assertEqual(call.call_count,1)

    def test_done_requires_every_signer_and_archives_each_pdf(self):
        api=FakeYousign(self.store,self.package)
        send_signature(self.store,self.rid,self.package,api,'Test'); api.status='done'
        with self.assertRaises(SignatureError): refresh_signature(self.store,self.rid,self.package,api)
        self.assertNotIn('completed_at',self.package['signature'])
        for p in api.people: p['status']='signed'
        refresh_signature(self.store,self.rid,self.package,api)
        self.assertIn('completed_at',self.package['signature'])
        self.assertTrue(all(self.store.path(d['signed_pdf']).is_file() for d in self.package['documents'].values()))

    def test_unsigned_or_changed_pdf_never_reaches_wedof(self):
        api=FakeWedof()
        with self.assertRaises(WorkspaceError): advance_submission(self.store,self.rid,self.package,api,'Test')
        self.assertFalse(api.calls)
        self.signed()
        self.store.path(self.package['documents']['cerfa']['signed_pdf']).write_bytes(b'changed')
        with self.assertRaises(WorkspaceError): advance_submission(self.store,self.rid,self.package,api,'Test')
        self.assertFalse(api.calls)

    def test_wedof_simulates_then_submits_once_and_manual_deposit_remains_due(self):
        self.signed();api=FakeWedof()
        for _ in range(9): result=advance_submission(self.store,self.rid,self.package,api,'Test')
        self.assertTrue(result['done'])
        calls=[c for c in api.calls if c[1].endswith('/submit')]
        self.assertEqual([c[3] for c in calls],[{'simulate':'true'},None])
        cerfa=calls[-1][2]['draftRawData']['cerfa']
        self.assertEqual(cerfa['formation']['dateFinFormation'][:10],self.package['values']['exam_end'])
        self.assertEqual(cerfa['apprenti']['responsableLegal']['prenom'],'Camille')
        self.assertEqual(cerfa['employeur']['codeIdcc'],'1351')
        self.assertTrue(cerfa['CERFASignatureProbante'])
        self.assertFalse(self.package['opco']['manual_deposit'])
        before=len(api.calls);advance_submission(self.store,self.rid,self.package,api,'Test')
        self.assertEqual(before,len(api.calls))

    def test_ambiguous_mutation_cannot_be_retried_without_reconciliation(self):
        self.signed();api=FakeWedof()
        advance_submission(self.store,self.rid,self.package,api,'Test')
        with patch.object(api,'call',return_value={}) as call:
            with self.assertRaises(WedofApiError): advance_submission(self.store,self.rid,self.package,api,'Test')
            self.assertEqual(self.store.package(self.rid)['opco']['pending'],'training_id')
            with self.assertRaises(WorkspaceError): advance_submission(self.store,self.rid,self.package,api,'Test')
            self.assertEqual(call.call_count,1)

    def test_distanciel_and_major_have_only_relevant_documents_and_signers(self):
        self.package=fake_package(self.store,'distanciel')
        self.package['values']['apprentice_birth_date']='1990-01-01'
        for d in self.package['documents'].values(): d['fields']=[f for f in d['fields'] if f['role']!='guardian']
        api=FakeYousign(self.store,self.package)
        send_signature(self.store,self.rid,self.package,api,'Test')
        self.assertEqual(len(api.docs),2);self.assertEqual(len(api.people),2)


class DocumentTests(unittest.TestCase):
    def test_nir_key_for_convergence_keeps_the_cerfa_identity_including_corsica(self):
        self.assertEqual(nir_with_key('2951099126111'), '295109912611193')
        self.assertEqual(nir_with_key('253072A073004'), '253072A07300443')
        self.assertEqual(nir_with_key('253072B073004'), '253072B07300470')

    def test_flattening_preserves_cerfa_background_values_and_checkboxes(self):
        content, fields=prepare_cerfa(complete_values(),assets())
        reader=PdfReader(io.BytesIO(content))
        self.assertEqual(len(reader.pages),2)
        text=' '.join(p.extract_text() for p in reader.pages)
        for expected in ['EXEMPLE','Élodie','DUPONT','802','41000']: self.assertIn(expected,text)
        self.assertTrue(all(len(p.extract_text())>2000 for p in reader.pages))
        self.assertFalse(reader.get_fields())
        self.assertTrue(all(not p.get('/Annots') for p in reader.pages))
        self.assertEqual({f['role'] for f in fields},{'employer','apprentice','guardian'})

    @unittest.skipUnless(shutil.which('libreoffice') or shutil.which('soffice'),'LibreOffice required for PDF layout check')
    def test_supplied_templates_generate_complete_pdfs_without_merge_or_signature_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ContractStore(Path(directory)/'bts.sqlite')
            values=complete_values()
            values.update(cfa_siret='84089988400026', cfa_uai='0831774C')
            package=generate_documents(store,'l-test',values,settings(values),assets())
            for kind,d in package['documents'].items():
                text=' '.join(p.extract_text() for p in PdfReader(store.path(d['pdf'])).pages)
                self.assertNotIn('BTSMARK',text);self.assertNotIn('«NOM_',text)
                self.assertIn('EXEMPLE',text)
            self.assertEqual({f['role'] for f in package['documents']['formation']['fields']},{'employer'})
            self.assertEqual({f['role'] for f in package['documents']['mobilite']['fields']},{'employer','apprentice','guardian'})
            values['apprentice_birth_date']='1990-01-01'
            remote=generate_documents(store,'l-test',values,settings(values,'distanciel'),assets())
            self.assertEqual(set(remote['documents']),{'cerfa','formation'})
            txt=' '.join(p.extract_text() for p in PdfReader(store.path(remote['documents']['formation']['pdf'])).pages)
            self.assertIn('À distance',txt)
            self.assertIn('0,00 €',txt)

    def test_guardian_is_determined_from_birthdate_and_emancipation(self):
        values=complete_values()
        self.assertTrue(needs_guardian(values,dt.date(2026,9,14)))
        values['apprentice_emancipated']='yes';self.assertFalse(needs_guardian(values,dt.date(2026,9,14)))
        with self.assertRaises(WorkspaceError):validate_settings({'teaching_mode':'invalid'})
        with self.assertRaises(WorkspaceError):validate_settings({'mobility_start':'2027-11-12','mobility_end':'2027-11-08'})


class ImportAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.legacy=make_legacy(self.tmp.name)
        self.legacy.app.add_url_rule('/webhooks/yousign','webhooks_yousign',lambda: ('legacy',401),methods=['POST'])
        register_bts_workspace(self.legacy)
        self.store=ContractStore(self.legacy.AKTO_BTS_DB_FILE);self.client=self.legacy.app.test_client()
        with self.client.session_transaction() as state:state.update(admin_logged_in=True,admin_role='admin')
        self.client.get('/admin/BTS/nouveau')
        with self.client.session_transaction() as state:self.csrf={'bts_csrf_token':state['bts_csrf_token']}

    def test_import_is_idempotent_private_and_keeps_source_details(self):
        candidate=dict(id='candidate-test',prenom='Élodie',nom='EXEMPLE',email='elodie@example.test',bts='MOS',mode='Présentiel',
            num_secu='209068312345600',nationalite='Française',resp_prenom='Camille',resp_nom='EXEMPLE',resp_email='parent@example.test',
            projet_objectif='Une information disponible',date_naissance='2009-06-12',sexe='F')
        with patch('bts_contract_routes.InscriptionsClient') as api:
            api.return_value.candidate.return_value=candidate
            response=self.client.post('/admin/BTS/inscriptions/importer',data={**self.csrf,'candidate_id':candidate['id']})
        self.assertEqual(response.status_code,302)
        rid=response.location.split('/dossiers/')[1].split('?')[0]
        again,created=self.store.import_candidate(candidate,'Test')
        self.assertEqual(again,rid);self.assertFalse(created)
        values=effective_values(self.store.record(rid),self.store.cerfa_complements(rid)['values'])
        self.assertEqual(values['apprentice_nir'],'2090683123456')
        self.assertEqual(self.store.settings(rid)['values']['teaching_mode'],'presentiel')
        self.assertNotIn('2090683123456',json.dumps(self.store.export_workspace()))
        self.assertNotIn('num_secu',self.store.imported(rid)['values'])
        page=self.client.get('/admin/BTS/dossiers/'+rid+'?tab=etudiant')
        self.assertIn('Une information disponible',page.text)

    def test_new_routes_require_session_writer_and_csrf(self):
        path='/admin/BTS/inscriptions/rechercher'
        self.assertEqual(self.client.post(path,data={'q':'Test'}).status_code,400)
        with self.client.session_transaction() as state:state['admin_role']='viewer'
        self.assertEqual(self.client.post(path,data={**self.csrf,'q':'Test'}).status_code,403)
        with self.client.session_transaction() as state:state.clear()
        self.assertEqual(self.client.post(path,data={**self.csrf,'q':'Test'}).status_code,302)

    def test_stale_package_does_not_call_yousign(self):
        rid=self.store.create_local({'apprentice_first_name':'Test','apprentice_last_name':'EXEMPLE'})
        package=fake_package(self.store);self.store.save_package(rid,package)
        with patch('bts_contract_routes.YousignClient',side_effect=AssertionError('Must not call')):
            response=self.client.post('/admin/BTS/dossiers/'+rid+'/signature/envoyer',data={**self.csrf,'package_id':package['id'],'reviewed':'yes'})
        self.assertEqual(response.status_code,302)

    def test_bts_webhook_uses_existing_hmac_before_looking_up_or_refreshing_signatures(self):
        self.legacy._verify_yousign_webhook_signature=lambda body: False
        package=fake_package(self.store)
        package['signature']['request_id']=str(uuid.uuid4())
        self.store.save_package('l-test',package)
        payload={'data':{'signature_request':{'id':package['signature']['request_id']}}}
        with patch('bts_contract_routes.YousignClient') as api, patch('bts_contract_routes.refresh_signature') as refresh:
            self.assertEqual(self.client.post('/webhooks/yousign',json=payload).status_code,401)
            refresh.assert_not_called();api.assert_not_called()
            self.legacy._verify_yousign_webhook_signature=lambda body: True
            self.assertEqual(self.client.post('/webhooks/yousign',json=payload).status_code,200)
            refresh.assert_called_once()


if __name__ == '__main__':unittest.main()
