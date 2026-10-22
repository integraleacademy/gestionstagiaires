"""Outreach imports and sending are explicit, isolated, durable and retry-safe."""
import io
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

import pytest
import app as host
import partner_campaigns as outreach


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('PARTNER_POSTGRES_MODE', 'off')
    monkeypatch.setenv('APP_BASE_URL', 'https://gestionstagiaires-r5no.onrender.com')
    for key, value in {'PERSIST_DIR':str(tmp_path), 'DATA_FILE':str(tmp_path/'data.json'), 'BACKUP_DIR':str(tmp_path/'backups'), 'UPLOADS_DIR':str(tmp_path/'uploads')}.items():
        monkeypatch.setattr(host,key,value)
    (tmp_path/'backups').mkdir()
    (tmp_path/'uploads').mkdir()
    (tmp_path/'data.json').write_text(json.dumps({'sessions':[], 'partners':[host._integrale_partner()], 'users':[], 'activity_logs':[]}))
    monkeypatch.setitem(host.app.config,'TESTING',True)
    monkeypatch.setitem(host.app.config,'SECRET_KEY','campaign-test-secret')
    monkeypatch.setattr(host,'BREVO_API_KEY','test-placeholder')
    monkeypatch.setattr(host,'BREVO_SENDER_EMAIL','sender@example.test')
    monkeypatch.setattr(host,'BREVO_SENDER_NAME','Test')
    mails=[]
    def send(*args,**kwargs):
        mails.append((args,kwargs))
        return {'ok':True,'message_id':'test-message'}
    monkeypatch.setattr(host,'brevo_send_email',send)
    client=host.app.test_client()
    with client.session_transaction() as sess:
        sess.update(admin_logged_in=True,admin_role='super_admin',platform_role='super_admin',partner_id=host.INTEGRALE_PARTNER_ID,admin_username='admin@example.test')
    page=client.get('/admin/partners?tab=campaigns')
    assert page.status_code==200
    token=re.search(r'name="csrf_token" value="([^"]+)"',page.text)[1]
    return client,token,mails


def stage(client,token,text,filename='contacts.csv'):
    res=client.post('/admin/partners/campaigns/import',data={'csrf_token':token,'contacts_file':(io.BytesIO(text.encode('utf-8-sig')),filename)})
    assert res.status_code==303
    return parse_qs(urlsplit(res.location).query)['import'][0]


def seed(setup):
    client,token,mails=setup
    iid=stage(client,token,'email;centre\nA@exemple.fr;Centre A\nb@exemple.fr;Centre B\n')
    assert client.post(f'/admin/partners/campaigns/import/{iid}/confirm',data={'csrf_token':token}).status_code==303
    with outreach.db(host) as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM outreach_contacts ORDER BY email')]


def create(setup,**extra):
    client,token,_=setup
    form={'csrf_token':token,'selection':'all','request_key':'a'*32,**extra}
    res=client.post('/admin/partners/campaigns/create',data=form)
    assert res.status_code==303
    return parse_qs(urlsplit(res.location).query)['campaign'][0]


def test_csv_and_paste_normalisation_and_bounds():
    result=outreach.parse_import('email;centre\nCONTACT@exemple.fr;École\ncontact@exemple.fr;Doublon\ninvalide;Centre\n'.encode('cp1252'),'export.csv')
    assert result['contacts']==[{'email':'contact@exemple.fr','centre':'École'}]
    assert result['duplicates']==1 and len(result['invalid'])==1
    pasted=outreach.parse_import(b'A@exemple.fr; b@exemple.fr\nNom <c@exemple.fr>')
    assert len(pasted['contacts'])==3
    assert not outreach.valid_email('a@exemple.fr\r\nBcc:b@exemple.fr')
    assert not outreach.valid_email('a..b@exemple.fr')
    assert not outreach.valid_email('valid@example.fr <evil@other.fr> junk')
    with pytest.raises(ValueError):outreach.parse_import(b'x'*(outreach.MAX_BYTES+1))
    with pytest.raises(ValueError):outreach.parse_import(b'x\n'*(outreach.MAX_CONTACTS+2))


def test_import_preview_confirm_dedup_and_no_accounts_or_sends(setup):
    client,token,mails=setup
    iid=stage(client,token,'email;centre\nA@exemple.fr;Centre A\na@exemple.fr;Dup\ninvalide;Erreur\n')
    with outreach.db(host) as conn:assert conn.execute('SELECT count(*) FROM outreach_contacts').fetchone()[0]==0
    preview=client.get('/admin/partners?tab=campaigns&import='+iid)
    assert 'nouveaux contacts' in preview.text and 'Adresses à corriger' in preview.text
    for _ in range(2):client.post(f'/admin/partners/campaigns/import/{iid}/confirm',data={'csrf_token':token})
    with outreach.db(host) as conn:assert conn.execute('SELECT count(*) FROM outreach_contacts').fetchone()[0]==1
    assert not mails
    data=json.loads(open(host.DATA_FILE).read())
    assert data['users']==[] and len(data['partners'])==1


def test_authentication_csrf_and_partner_assistance_guards(setup):
    client,token,mails=setup
    base='/admin/partners/campaigns'
    for path in ('/template','/test','/import','/create','/unknown/start','/unknown/next','/unknown/pause'):
        assert client.post(base+path).status_code==400
    with client.session_transaction() as sess:sess['assist_partner_id']='other'
    assert client.get(base+'/preview').status_code==403
    assert client.post(base+'/import',data={'csrf_token':token,'contacts_text':'a@exemple.fr'}).status_code==403
    with client.session_transaction() as sess:sess.clear()
    assert client.get(base+'/preview').status_code in (302,401)
    assert not mails


def test_template_escaping_snapshots_and_individual_delivery(setup):
    client,token,mails=setup
    contacts=seed(setup)
    template={**outreach.DEFAULT_TEMPLATE,'intro':'<script>alert(1)</script> Une démonstration ?','subject':'Le test & son rendu','aps_price':'59,50'}
    assert client.post('/admin/partners/campaigns/template',data={'csrf_token':token,**template}).status_code==303
    preview=client.get('/admin/partners/campaigns/preview')
    assert '&lt;script&gt;' in preview.text and '<script>' not in preview.text
    assert '59,50 €' in preview.text and '/static/images/learner-welcome-aps-email.jpg' in preview.text
    cid=create(setup)
    assert create(setup)==cid
    assert not mails
    client.post('/admin/partners/campaigns/template',data={'csrf_token':token,**outreach.DEFAULT_TEMPLATE,'subject':'Later change'})
    base='/admin/partners/campaigns/'+cid
    assert client.post(base+'/next',data={'csrf_token':token}).json['done']
    assert client.post(base+'/start',data={'csrf_token':token}).status_code==400
    assert not mails
    assert client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'}).status_code==200
    for _ in range(4):assert client.post(base+'/next',data={'csrf_token':token}).status_code==200
    assert len(mails)==2
    assert mails[0][0][0]=='a@exemple.fr' and mails[0][0][1]=='Le test & son rendu'
    assert 'b@exemple.fr' not in mails[0][0][2]
    assert '/communications/desinscription/' in mails[0][0][2]
    assert mails[0][1]['reply_to']['email']=='clement@integraleacademy.com'
    assert mails[0][1]['metadata']['idempotency_key']!=mails[1][1]['metadata']['idempotency_key']
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    client.post(base+'/next',data={'csrf_token':token})
    assert len(mails)==2


def test_unsubscribe_is_confirmed_and_survives_reimport_and_draft(setup):
    client,token,mails=setup
    contacts=seed(setup)
    cid=create(setup)
    link='/communications/desinscription/'+contacts[0]['unsubscribe_token']
    assert client.get(link).status_code==200
    with outreach.db(host) as conn:assert not conn.execute('SELECT unsubscribed_at FROM outreach_contacts WHERE id=?',(contacts[0]['id'],)).fetchone()[0]
    assert client.post(link).status_code==200
    iid=stage(client,token,'email\na@exemple.fr\n')
    client.post(f'/admin/partners/campaigns/import/{iid}/confirm',data={'csrf_token':token})
    base='/admin/partners/campaigns/'+cid
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    for _ in range(4):client.post(base+'/next',data={'csrf_token':token})
    assert len(mails)==1 and mails[0][0][0]=='b@exemple.fr'
    assert client.get(base+'/status').json['counts']['skipped']==1


def test_failed_and_ambiguous_results_pause_without_resending(setup,monkeypatch):
    client,token,mails=setup
    seed(setup)
    cid=create(setup)
    base='/admin/partners/campaigns/'+cid
    monkeypatch.setattr(host,'brevo_send_email',lambda *a,**k:{'ok':False,'status_code':429,'error':'quota'})
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    result=client.post(base+'/next',data={'csrf_token':token}).json
    assert result['status']=='paused' and result['counts']['failed']==1
    monkeypatch.setattr(host,'brevo_send_email',lambda *a,**k:{'ok':False,'status_code':None,'error':'timeout'})
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    result=client.post(base+'/next',data={'csrf_token':token}).json
    assert result['counts']['uncertain']==1 and result['status']=='paused'
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    result=client.post(base+'/next',data={'csrf_token':token}).json
    assert result['done'] and result['counts']['uncertain']==1


def test_stale_claim_and_pause_and_resend_filter(setup):
    client,token,mails=setup
    contacts=seed(setup)
    cid=create(setup)
    base='/admin/partners/campaigns/'+cid
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    with outreach.db(host,True) as conn:
        conn.execute("UPDATE outreach_deliveries SET status='sending',started=? WHERE campaign_id=? AND contact_id=?",(time.time(),cid,contacts[0]['id']))
    assert client.post(base+'/next',data={'csrf_token':token}).json['busy']
    assert not mails
    with outreach.db(host,True) as conn:conn.execute("UPDATE outreach_deliveries SET started=0 WHERE status='sending'")
    client.post(base+'/start',data={'csrf_token':token,'confirm':'yes'})
    client.post(base+'/pause',data={'csrf_token':token})
    assert client.post(base+'/next',data={'csrf_token':token}).json['done']
    assert not mails
    cid2=create(setup,request_key='b'*32)
    assert client.get('/admin/partners/campaigns/'+cid2+'/status').json['total']==1


def test_single_test_send_saves_copy_and_results_export_is_safe(setup):
    client,token,mails=setup
    seed(setup)
    with outreach.db(host,True) as conn:
        previous={**outreach.DEFAULT_TEMPLATE,**outreach.PREVIOUS_TEMPLATE_COPY,'aps_price':'65'}
        conn.execute('INSERT INTO outreach_settings (id,payload) VALUES (1,?)',(json.dumps(previous),))
        refreshed=outreach.saved_template(conn)
        assert refreshed['subject']==outreach.DEFAULT_TEMPLATE['subject']
        assert refreshed['intro']==outreach.DEFAULT_TEMPLATE['intro']
        assert refreshed['aps_price']=='65'
    form={**outreach.DEFAULT_TEMPLATE,'subject':'Mon modèle modifié','intro':'Mon introduction personnalisée','test_email':'test@exemple.fr','csrf_token':token}
    assert client.post('/admin/partners/campaigns/test',data=form).status_code==303
    assert len(mails)==1 and mails[0][0][0]=='test@exemple.fr'
    assert mails[0][0][1]=='[TEST] Mon modèle modifié'
    assert 'href="https://integraleconnect.com"' in mails[0][0][2]
    assert 'mailto:clement@integraleacademy.com?subject=' not in mails[0][0][2]
    assert 'Demander une démonstration : https://integraleconnect.com' in mails[0][1]['text_content']
    with outreach.db(host,True) as conn:
        assert outreach.saved_template(conn)['subject']=='Mon modèle modifié'
        assert outreach.saved_template(conn)['intro']=='Mon introduction personnalisée'
        conn.execute("UPDATE outreach_contacts SET centre='=1+1'")
    cid=create(setup)
    report=client.get('/admin/partners/campaigns/'+cid+'/results.csv')
    assert report.status_code==200 and "'=1+1" in report.text
    assert 'a@exemple.fr' in report.text and 'b@exemple.fr' in report.text
    assert len(mails)==1


def test_entire_list_is_not_limited_by_pagination_or_import_size(setup):
    client,token,mails=setup
    with outreach.db(host,True) as conn:
        conn.executemany('INSERT INTO outreach_contacts (id,email,centre,batch_id,created_at,unsubscribe_token) VALUES (?,?,?,?,?,?)',
            [(f'bulk-{i}',f'centre-{i:05d}@exemple.fr','Centre sécurité','bulk',outreach.now(),f'token-{i}') for i in range(5001)])
    page=client.get('/admin/partners?tab=campaigns')
    assert page.text.count('name="contact_id"')==100
    assert '<option value="all" selected>' in page.text
    assert 'data-total="5001" data-eligible="5001"' in page.text
    cid=create(setup)
    status=client.get('/admin/partners/campaigns/'+cid+'/status').json
    assert status['total']==5001 and status['counts']['pending']==5001 and status['status']=='draft'
    assert not mails


def test_bulk_selection_respects_search_import_and_contact_exclusions(setup):
    client,token,mails=setup
    with outreach.db(host,True) as conn:
        conn.executemany('INSERT INTO outreach_contacts (id,email,centre,batch_id,created_at,unsubscribe_token) VALUES (?,?,?,?,?,?)',
            [(f'scope-{i}',f'scope-{i:03d}@exemple.fr','Sécurité_100%','batch-a',outreach.now(),f'scope-token-{i}') for i in range(130)]
            + [('other-batch','other-batch@exemple.fr','Sécurité_100%','batch-b',outreach.now(),'other-batch-token'),
               ('other-centre','other-centre@exemple.fr','SécuritéA100x','batch-a',outreach.now(),'other-centre-token')])
        conn.execute("UPDATE outreach_contacts SET unsubscribed_at=? WHERE id='scope-0'",(outreach.now(),))
        conn.execute('INSERT INTO outreach_campaigns (id,name,template,created_at,request_key) VALUES (?,?,?,?,?)',
            ('previous','Précédente',json.dumps(outreach.DEFAULT_TEMPLATE),outreach.now(),'previous-request'))
        conn.executemany('INSERT INTO outreach_deliveries (campaign_id,contact_id,status) VALUES (?,?,?)',
            [('previous',f'scope-{i}',state) for i,state in enumerate(('sent','sending','uncertain'),1)])
    scope={'batch':'batch-a','contacts_q':'Sécurité_100%'}
    page=client.get('/admin/partners',query_string={'tab':'campaigns',**scope})
    assert 'data-total="129" data-eligible="126"' in page.text
    cid=create(setup,**scope)
    with outreach.db(host) as conn:
        recipients={r[0] for r in conn.execute('SELECT contact_id FROM outreach_deliveries WHERE campaign_id=?',(cid,))}
    assert recipients=={f'scope-{i}' for i in range(4,130)}
    cid2=create(setup,request_key='b'*32,include_contacted='yes',**scope)
    assert client.get('/admin/partners/campaigns/'+cid2+'/status').json['total']==129
    cid3=create(setup,request_key='c'*32,selection='selected',contact_id=['scope-4','other-batch','other-centre'],**scope)
    assert client.get('/admin/partners/campaigns/'+cid3+'/status').json['total']==1
    assert not mails
