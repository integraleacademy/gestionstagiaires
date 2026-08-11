import io, unittest
from unittest.mock import patch
from PIL import Image
import afc_import
import app as gestion_app

def image_bytes():
    out=io.BytesIO(); Image.new('RGB',(20,20),'white').save(out,'PNG'); return out.getvalue()

SAMPLE=[
 {'france_travail_id':'5216923U - 032','last_name':'BENBEGHILA CHERIF','first_names':'Soraya Hadria','phone':'06 02 40 43 09','email':'SORAYA@EXAMPLE.COM','department':'Var (83)','warnings':[]},
 {'france_travail_id':'5873509Z-032','last_name':'LOY','first_names':'Morwenna Marina Morrigane','phone':'+33 7 64 28 12 39','email':'MORWENNA@EXAMPLE.COM','warnings':[]},
]

class AfcImageImportTests(unittest.TestCase):
 def setUp(self): self.client=gestion_app.app.test_client(); self.data={'afc':{'candidates':[]}}
 def login(self):
  with self.client.session_transaction() as s: s['admin_logged_in']=True; s['admin_role']='admin'
 def preview(self,candidates=SAMPLE,content=None):
  self.login()
  with patch.object(gestion_app,'load_data',return_value=self.data),patch.object(afc_import,'analyze_image',return_value=candidates):
   return self.client.post('/admin/afc/import-image/preview',data={'image':(io.BytesIO(content or image_bytes()),'capture.png')},content_type='multipart/form-data')
 def test_non_admin_cannot_use_routes(self):
  self.assertEqual(self.client.post('/admin/afc/import-image/preview').status_code,302)
  self.assertEqual(self.client.post('/admin/afc/import-image/confirm',json={'candidates':[]}).status_code,302)
 def test_preview_does_not_create_and_preserves_names(self):
  body=self.preview().get_json(); self.assertEqual(body['summary']['detected'],2); self.assertEqual(self.data['afc']['candidates'],[])
  self.assertEqual(body['candidates'][0]['last_name'],'BENBEGHILA CHERIF'); self.assertEqual(body['candidates'][1]['first_names'],'Morwenna Marina Morrigane'); self.assertEqual(body['candidates'][0]['email'],'soraya@example.com')
 def test_invalid_image(self):
  r=self.preview(content=b'not image'); self.assertEqual(r.status_code,400); self.assertIn('image valide',r.get_json()['message'])
 def test_too_large(self):
  self.login(); r=self.client.post('/admin/afc/import-image/preview',data={'image':(io.BytesIO(b'x'*(afc_import.MAX_IMAGE_BYTES+1)),'x.png')},content_type='multipart/form-data'); self.assertIn(r.status_code,(400,413))
 def test_normalizations(self):
  self.assertEqual(afc_import.normalize_ft_id('5216923u 032')[0],afc_import.normalize_ft_id('5216923U - 032')[0]); self.assertEqual(afc_import.normalize_phone('+33 6 02 40 43 09')[0],afc_import.normalize_phone('06 02 40 43 09')[0])
 def test_ft_identifier_is_valid_with_or_without_three_digit_suffix(self):
  short={**SAMPLE[0],'france_travail_id':'5216923U'}
  long={**SAMPLE[0],'france_travail_id':'5216923U - 032'}
  self.assertEqual(gestion_app._afc_classify_import_candidates([short],[])[0]['status'],'ready')
  self.assertEqual(gestion_app._afc_classify_import_candidates([long],[])[0]['status'],'ready')
  self.assertEqual(afc_import.normalize_ft_id(short['france_travail_id'])[0],afc_import.normalize_ft_id(long['france_travail_id'])[0])
 def test_short_ft_identifier_detects_existing_long_identifier(self):
  existing=[{'id':'AFC-X','identifiant_ft':'5216923U - 032'}]
  row=gestion_app._afc_classify_import_candidates([{**SAMPLE[0],'france_travail_id':'5216923U'}],existing)[0]
  self.assertEqual(row['status'],'duplicate'); self.assertIn('Identifiant',row['reason'])
 def test_duplicates_by_strong_identifiers(self):
  base={'id':'AFC-X','identifiant_ft':'5216923U-032','email':'old@example.com','telephone':'06 01 02 03 04'}
  cases=[({'france_travail_id':'5216923u 032','email':'new@example.com','phone':'0611111111'},'Identifiant'),({'france_travail_id':'1111111A-001','email':'OLD@EXAMPLE.COM','phone':'0611111111'},'e-mail'),({'france_travail_id':'1111111A-001','email':'new@example.com','phone':'+33 6 01 02 03 04'},'téléphone')]
  for changed,reason in cases:
   row=gestion_app._afc_classify_import_candidates([{**SAMPLE[0],**changed}],[base])[0]; self.assertEqual(row['status'],'duplicate'); self.assertIn(reason,row['reason'])
 def test_archived_candidate_does_not_block_a_new_import(self):
  archived={'id':'AFC-ARCHIVED','identifiant_ft':'5216923U-032','email':'soraya@example.com','telephone':'0602404309','archived':True}
  row=gestion_app._afc_classify_import_candidates([SAMPLE[0]],[archived])[0]
  self.assertEqual(row['status'],'ready'); self.assertTrue(row['selected'])
 def test_confirmation_imports_candidate_already_in_archives(self):
  self.login(); persisted={'afc':{'candidates':[{'id':'AFC-ARCHIVED','identifiant_ft':'5216923U-032','email':'soraya@example.com','telephone':'0602404309','archived':True}]}}
  def atomic(mutator): return mutator(persisted)
  with patch.object(gestion_app,'_atomic_update_data',side_effect=atomic),patch.object(gestion_app,'fetch_cnaps_lookup_by_name',return_value={}),patch.object(gestion_app,'brevo_send_email',return_value=True),patch.object(gestion_app,'brevo_send_sms',return_value=True):
   result=self.client.post('/admin/afc/import-image/confirm',json={'candidates':[SAMPLE[0]],'date_icop':'2026-09-15'}).get_json()
  self.assertEqual(result['imported'],1); self.assertEqual(result['duplicates_skipped'],0); self.assertEqual(len(persisted['afc']['candidates']),2)
  self.assertTrue(persisted['afc']['candidates'][0]['archived']); self.assertFalse(persisted['afc']['candidates'][1].get('archived',False))
 def test_batch_duplicate_incomplete_corrected_and_conflict(self):
  rows=gestion_app._afc_classify_import_candidates([SAMPLE[0],dict(SAMPLE[0])],[]); self.assertEqual([r['status'] for r in rows],['ready','duplicate'])
  bad={**SAMPLE[0],'first_names':''}; self.assertEqual(gestion_app._afc_classify_import_candidates([bad],[])[0]['status'],'invalid'); bad['first_names']='Soraya Hadria'; self.assertEqual(gestion_app._afc_classify_import_candidates([bad],[])[0]['status'],'ready')
  existing=[{'id':'1','identifiant_ft':'5216923U032'},{'id':'2','email':'soraya@example.com'}]; self.assertEqual(gestion_app._afc_classify_import_candidates([SAMPLE[0]],existing)[0]['status'],'conflict')
 def test_selected_confirmation_is_idempotent(self):
  self.login(); persisted={'afc':{'candidates':[]}}
  def atomic(mutator): return mutator(persisted)
  with patch.object(gestion_app,'_atomic_update_data',side_effect=atomic),patch.object(gestion_app,'fetch_cnaps_lookup_by_name',return_value={}),patch.object(gestion_app,'brevo_send_email',return_value=True) as email,patch.object(gestion_app,'brevo_send_sms',return_value=True) as sms:
   first=self.client.post('/admin/afc/import-image/confirm',json={'candidates':[SAMPLE[0]],'date_icop':'2026-09-15'}).get_json(); second=self.client.post('/admin/afc/import-image/confirm',json={'candidates':[SAMPLE[0]],'date_icop':'2026-09-15'}).get_json()
  self.assertEqual(first['imported'],1); self.assertEqual(second['imported'],0); self.assertEqual(second['duplicates_skipped'],1); self.assertEqual(len(persisted['afc']['candidates']),1)
  candidate=persisted['afc']['candidates'][0]; self.assertEqual(candidate['date_icop'],'2026-09-15'); self.assertEqual(candidate['presence_afc_status'],'CONVOQUE'); self.assertEqual(candidate['notification_status'],'ENVOYEE'); email.assert_called_once(); sms.assert_called_once()
  self.assertEqual(candidate['convocation_email_status'],'ACCEPTE'); self.assertEqual(candidate['convocation_sms_status'],'ACCEPTE')
  self.assertTrue(candidate['convocation_email_sent_at']); self.assertEqual(candidate['convocation_email_sent_at'],candidate['convocation_sms_sent_at'])
 def test_convocation_records_each_channel_failure(self):
  candidate={'email':'personne@example.com','telephone':'06 01 02 03 04','prenom':'Jean','nom':'DUPONT','date_icop':'2026-09-15'}
  with patch.object(gestion_app,'brevo_send_email',return_value=True),patch.object(gestion_app,'brevo_send_sms',return_value=False):
   ok,error=gestion_app._send_afc_convocation_notification({'mail_templates':{}},candidate)
  self.assertFalse(ok); self.assertIn('Échec',error)
  self.assertEqual(candidate['convocation_email_status'],'ACCEPTE'); self.assertTrue(candidate['convocation_email_sent_at'])
  self.assertEqual(candidate['convocation_sms_status'],'ECHEC'); self.assertEqual(candidate['convocation_sms_sent_at'],'')
 def test_afc_page_displays_separate_provider_acceptance_statuses(self):
  self.login(); self.data={'afc':{'candidates':[{'id':'AFC-1','nom':'DUPONT','prenom':'Jean','email':'personne@example.com','telephone':'0601020304','convocation_email_status':'ACCEPTE','convocation_sms_status':'ECHEC','convocation_email_sent_at':'2026-08-04T12:00:00Z'}]}}
  with patch.object(gestion_app,'load_data',return_value=self.data),patch.object(gestion_app,'fetch_cnaps_lookup_by_name',return_value={}):
   html=self.client.get('/admin/afc').get_data(as_text=True)
  self.assertIn('E-mail accepté',html); self.assertIn('SMS en échec',html); self.assertIn('sans garantie de lecture',html)
 def test_confirmation_requires_icop_date(self):
  self.login(); response=self.client.post('/admin/afc/import-image/confirm',json={'candidates':[SAMPLE[0]]}); self.assertEqual(response.status_code,400); self.assertIn('date ICOP',response.get_json()['message'])
 def test_provider_error_readable(self):
  self.login()
  with patch.object(afc_import,'analyze_image',side_effect=afc_import.AfcVisionError(afc_import.GENERIC_ANALYSIS_ERROR)):
   r=self.client.post('/admin/afc/import-image/preview',data={'image':(io.BytesIO(image_bytes()),'x.png')},content_type='multipart/form-data')
  self.assertEqual(r.status_code,422); self.assertIn('nette',r.get_json()['message'])

if __name__=='__main__': unittest.main()
